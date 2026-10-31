"""The connector against a real MoolaKata (requirements S18.4–S18.8): paired from a code,
reporting, collecting a credential the owner sealed, running OFX Direct Connect against a bank
and posting what it found through the import, a post refused for a limit kept for a later run,
and unpairing. MoolaKata runs in-process; the connector's HTTPS transport is wired to it, and
the bank's server answers from the test."""

import json

import pytest
from moolakata_connector import client
from moolakata_connector.core import Core
from server_conftest import ORIGIN, make_user, sign_in

from moolakata import ids

BANK = "ofx.cu.example"
BANK2 = "ofx2.cu.example"  # where the credit union moved its server


def keys_short(core) -> str:
    from moolakata_connector import keys

    return keys.short(core.pairing.fingerprint)


class Wired(client.Transport):
    """The connector's requests delivered to MoolaKata's app in-process; the bank's OFX server
    answers with what `bank` holds."""

    def __init__(self, app_client, egress):
        super().__init__(egress)
        self.app = app_client
        self.bank = {"ofx": OFX}
        self.asked: list[str] = []  # the banks' hosts asked, in order

    def request(self, method, url, headers, body, pins=None):
        from urllib.parse import urlsplit

        u = urlsplit(url)
        self.egress.check(u.hostname or "")
        if u.hostname in (BANK, BANK2):
            self.asked.append(u.hostname)
            return client.Answer(200, {}, self.bank["ofx"])
        r = self.app.request(method, u.path, content=body, headers=headers)
        return client.Answer(r.status_code, dict(r.headers), r.content)


@pytest.fixture
def money(server, admin_client, client):
    from moolakata import settings

    with server.db.tx() as s:
        settings.put(s, "publicUrl", ORIGIN, None)
    return server, admin_client, client


def test_the_connector_pairs_reports_collects_and_posts(money, tmp_path):
    from moolakata.connector import sealed as mk_sealed
    from moolakata.links import keys as mk_keys
    from moolakata.store.entities.accounts import Account, Transaction

    server, admin, app = money
    core = Core(tmp_path / "data", transport=None)
    core.transport = Wired(app, core.egress)
    phrase = " ".join(core.vault.create())

    # Pair from the code Settings shows, with the vault unlocked (the sealing key goes into
    # it); both sides show the same fingerprint.
    code = admin.post("/ui/api/settings/connector/pairings").json()["code"]
    shown = core.pair(code)
    view = admin.get("/ui/api/settings/connector").json()
    assert view["state"] == "paired" and view["fingerprint"] == shown
    assert "sealingPublic" in (tmp_path / "data" / "pairing.json").read_text()
    # B31: a pairing MoolaKata refuses (the code is used) leaves the working one as it was.
    before = (tmp_path / "data" / "pairing.json").read_bytes()
    with pytest.raises(client.ServerError):
        core.pair(code)
    assert (tmp_path / "data" / "pairing.json").read_bytes() == before
    assert keys_short(core) == shown
    # Until an admin confirms the fingerprints match, a posted file waits (S18.4.3).
    assert admin.post("/ui/api/settings/connector/confirm").status_code == 200
    core.vault.lock()
    # A locked connector reports so, and MoolaKata alerts.
    core.tick()
    assert admin.get("/ui/api/settings/connector").json()["locked"] is True

    # Alice makes a Connection to her credit union and syncs her checking account to it.
    alice = make_user(server, "alice").id
    c = sign_in(server, "alice")
    # The connection made as the profile's dialog makes it, through the save (S13.8.11).
    settings = {"url": f"https://{BANK}/ofx", "org": "CU", "fid": "1",
                "accountType": "CHECKING", "accountId": "4417"}  # fmt: skip
    fields = {"driver": "ofx-direct", "label": "Credit union", "settings": settings}
    made = {"op": "create", "entity": "Conn", "id": ids.new_id("Conn"), "fields": fields}
    r = c.post("/ui/api/save", json={"ops": [made]})
    assert r.status_code == 200, r.text
    conn = r.json()["saved"][0]["record"]
    with server.db.tx() as s:
        a = Account(
            id="Acct_01m4zzbtececftrsacpbatewws", ownerId=alice, name="Checking", type="checking"
        )
        s.add(a)
    aid = "Acct_01m4zzbtececftrsacpbatewws"
    v = c.get(f"/ui/api/accounts/{aid}").json()["version"]
    # Its sync turned on as the account's Settings saves it (S13.8.11).
    fields = {"connectionId": conn["id"], "syncAccount": "Checking ••4417"}
    op = {"op": "update", "entity": "Acct", "id": aid, "version": v, "fields": fields}
    r = c.post("/ui/api/save", json={"ops": [op]})
    assert r.status_code == 200, r.text
    # Her sealed sign-in: collected once unlocked, then gone from MoolaKata.
    public = mk_keys.unb64(c.get("/ui/api/connector").json()["sealingKey"])
    box = mk_sealed.seal(
        json.dumps(
            {
                "credentials": {"username": "alice", "password": "pw"},
                "host": BANK,
                "sealedAt": 1792000000000,
            }
        ).encode(),
        public,
        conn["id"],
    )
    c.post(f"/ui/api/profile/connections/{conn['id']}/credential", json={"sealed": box})
    core.tick()
    # Locked, it reports with its status key only, and hears nothing of a Connection (S18.4.2).
    assert core.vault.locked and core.connections == {}
    assert c.get("/ui/api/profile/connections").json()["items"][0]["credentialWaiting"] is True
    core.unlock(phrase)
    core.tick()
    assert core.vault.get(conn["id"]) == {"username": "alice", "password": "pw"}
    assert c.get("/ui/api/profile/connections").json()["items"][0]["credentialWaiting"] is False
    state = core.connections[conn["id"]]
    assert state.state == "ok" and state.last_added == 2 and state.message == "1 statement"
    with server.db.read() as s:
        assert s.query(Transaction).filter_by(accountId=aid).count() == 2
    # The run is reported at once, and Settings shows it; nothing is posted twice.
    shown = admin.get("/ui/api/settings/connector").json()["connections"][0]
    assert shown["state"] == "ok" and shown["lastRunAt"]
    core.tick()
    with server.db.read() as s:
        assert s.query(Transaction).filter_by(accountId=aid).count() == 2

    # The owner's upload limit: the file waits for a later run.
    for _ in range(60):
        server.upload_rate.hit(alice)
    core.transport.bank["ofx"] = OFX.replace(b"20260912", b"20261002")
    state.last_run = None
    core.tick()
    assert len(state.backlog) == 1 and "upload limit" in (state.message or "")
    server.upload_rate.clear(alice)
    core.tick()
    assert state.backlog == []

    # CR3-70, S18.7.3: the credit union moves its server. Alice changes the address in the
    # credentials dialog, which saves it first, then seals the sign-in for the new host; the
    # connector files it bound there, and runs against the new server alone.
    conn = c.get("/ui/api/profile/connections").json()["items"][0]
    assert conn["host"] == BANK and conn["address"] == f"https://{BANK}/ofx"
    moved = {**conn["settings"], "url": f"https://{BANK2}/ofx"}
    fields = {"driver": "ofx-direct", "label": conn["label"], "settings": moved}
    op = {"op": "update", "entity": "Conn", "id": conn["id"], "version": conn["version"],
          "fields": fields}  # fmt: skip
    r = c.post("/ui/api/save", json={"ops": [op]})
    assert r.status_code == 200, r.text
    box = mk_sealed.seal(
        json.dumps({"credentials": {"username": "alice", "password": "pw2"}, "host": BANK2,
                    "sealedAt": 1792000001000}).encode(),
        public,
        conn["id"],
    )  # fmt: skip
    c.post(f"/ui/api/profile/connections/{conn['id']}/credential", json={"sealed": box})
    core.transport.asked.clear()
    state.last_run = None
    core.tick()
    assert core.vault.host(conn["id"]) == BANK2
    assert core.vault.get(conn["id"]) == {"username": "alice", "password": "pw2"}
    assert core.transport.asked == [BANK2] and state.state == "ok", state.message

    # Unpair from MoolaKata: the next report is refused and the connector's loop survives.
    admin.post("/ui/api/settings/connector/unpair")
    with pytest.raises(client.ServerError) as e:
        core.tick()
    assert e.value.code == "not-paired"
    core.unpair()
    assert core.pairing is None and core.vault.ids() == []


def test_a_server_that_isnt_the_one_paired_with_gets_nothing(money, tmp_path):
    _server, admin, app = money
    core = Core(tmp_path / "data", transport=None)
    core.transport = Wired(app, core.egress)
    core.vault.create()
    code = admin.post("/ui/api/settings/connector/pairings").json()["code"]
    bad = json.loads(client.unb64(code[5:]))
    bad["f"] = "0" * 64
    from moolakata_connector.keys import b64

    forged = "mkp1." + b64(json.dumps(bad).encode())
    with pytest.raises(client.ServerError) as e:
        core.pair(forged)
    assert e.value.code == "fingerprint-mismatch"
    assert admin.get("/ui/api/settings/connector").json()["state"] == "pairing"


def test_a_hello_naming_the_right_fingerprint_with_another_key_gets_nothing(
    money, tmp_path, monkeypatch
):
    # C23, S18.4.2: the key hello gives must itself hash to the code's fingerprint; a relay
    # repeating the fingerprint with a key of its own is refused before anything is sent.
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
    from moolakata_connector.keys import b64

    _server, admin, app = money
    core = Core(tmp_path / "data", transport=None)
    core.transport = Wired(app, core.egress)
    core.vault.create()
    code = admin.post("/ui/api/settings/connector/pairings").json()["code"]
    real = client.hello
    other = Ed25519PrivateKey.generate().public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    monkeypatch.setattr(client, "hello", lambda *a, **k: {**real(*a, **k), "key": b64(other)})
    with pytest.raises(client.ServerError) as e:
        core.pair(code)
    assert e.value.code == "fingerprint-mismatch"
    assert admin.get("/ui/api/settings/connector").json()["state"] == "pairing"


OFX = b"""OFXHEADER:100
DATA:OFXSGML
VERSION:102
SECURITY:NONE
ENCODING:USASCII
CHARSET:1252
COMPRESSION:NONE
OLDFILEUID:NONE
NEWFILEUID:NONE

<OFX><SIGNONMSGSRSV1><SONRS><STATUS><CODE>0<SEVERITY>INFO</STATUS><DTSERVER>20261001
<LANGUAGE>ENG</SONRS></SIGNONMSGSRSV1><BANKMSGSRSV1><STMTTRNRS><TRNUID>1<STATUS><CODE>0
<SEVERITY>INFO</STATUS><STMTRS><CURDEF>USD<BANKACCTFROM><BANKID>101000695<ACCTID>4417
<ACCTTYPE>CHECKING</BANKACCTFROM><BANKTRANLIST><DTSTART>20260901<DTEND>20260930
<STMTTRN><TRNTYPE>DEBIT<DTPOSTED>20260912<TRNAMT>-42.37<FITID>f1<NAME>SHELL</STMTTRN>
<STMTTRN><TRNTYPE>CREDIT<DTPOSTED>20260915<TRNAMT>2500.00<FITID>f2<NAME>PAYROLL</STMTTRN>
</BANKTRANLIST><LEDGERBAL><BALAMT>3457.63<DTASOF>20260930</LEDGERBAL></STMTRS></STMTTRNRS>
</BANKMSGSRSV1></OFX>
"""


def test_its_page_pairs_it_and_shows_the_confirmation(money, tmp_path):
    """S18.11: the welcome on its page, then Pair with the code and the words; MoolaKata learns
    the page's address from the report and links to it, and the page shows the pairing
    unconfirmed until an admin confirms it."""
    from moolakata_connector import page
    from test_page import call, free_port, make_vault

    _, admin, app = money
    data = tmp_path / "data"
    core = Core(data, transport=None)
    core.transport = Wired(app, core.egress)
    settings = page.Settings(port=free_port(), names=("127.0.0.1",))
    core.page = settings.address
    served = page.serve(core, settings, data)
    running = (core, settings, data / "tls" / "cert.pem")
    try:
        phrase = make_vault(running)
        core.lock()
        code = admin.post("/ui/api/settings/connector/pairings").json()["code"]
        status, _, text = call(running, "POST", "/pair", {"code": code, "words": phrase})
        assert status == 200, text
        view = admin.get("/ui/api/settings/connector").json()
        assert view["state"] == "paired" and view["fingerprint"] in text
        core.tick()
        assert admin.get("/ui/api/settings/connector").json()["page"] == settings.address
        assert "not confirmed yet" in call(running, "GET", "/")[2]
        assert admin.post("/ui/api/settings/connector/confirm").status_code == 200
        core.tick()
        text = call(running, "GET", "/")[2]
        assert "confirmed" in text and "not confirmed" not in text
    finally:
        served.shutdown()
        served.server_close()
