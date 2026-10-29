"""The MoolaKata Connector's side on the server (requirements S18.4–S18.8,
docs/connector-protocol.md): pairing from a one-time code, signed calls and signed answers,
reports and what they are answered with, sealed credentials, file posts through the import,
Settings › Connector, the address ranges of Settings › Network, and the alerts."""

import datetime as dt
import json

import pytest
from conftest import ORIGIN, make_user, new_client, sign_in

from moolakata import alerts, clock, exactjson, ids, settings
from moolakata.connector import PROTOCOL, manage
from moolakata.links import keys, signing
from moolakata.links.signing import Ed25519PrivateKey
from moolakata.store.entities.accounts import Account, Import, Transaction
from moolakata.store.entities.connector import Connection, Connector

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


class FakeConnector:
    """A connector as the protocol describes it: its identity key, signed calls to the server's
    app, and answers checked against the server's link key."""

    def __init__(self, server, client):
        self.key = Ed25519PrivateKey.generate()
        self.sealing = Ed25519PrivateKey.generate()  # any 32 raw bytes serve as a sealing key
        self.client = client
        with server.db.tx() as s:
            self.server_key = keys.public_of(s, server.keys.secrets)
        self.fp = keys.fingerprint(self.server_key)

    def call(self, path: str, data: dict | None = None, *, raw: bytes | None = None, headers=None):
        body = raw if raw is not None else exactjson.dumps(data or {}).encode()
        signed = signing.sign_request(self.key, "POST", path, body, self.fp, scheme=signing.CONN)
        h = {
            **signed.headers,
            "Content-Type": "application/json",
            "MK-Conn-Protocol": str(PROTOCOL),
            "MK-Conn-Version": "0.1.0-test",
            **(headers or {}),
        }
        r = self.client.post(path, content=body, headers=h)
        # The answer names this connector and this call (protocol §3.3).
        me = keys.fingerprint(keys.raw_public(self.key.public_key()))
        asked = signing.Asked(signed.nonce, me, signed.body_hash)
        signing.verify_answer(
            self.server_key, r.status_code, r.content, asked, r.headers, scheme=signing.CONN
        )
        return r

    def pair(self, code: str, signed: bool = True):
        from moolakata.connector.manage import SEALING_LABEL

        sealing = b"\x11" * 32
        signature = self.key.sign(SEALING_LABEL + sealing) if signed else b"\x00" * 64
        return self.call(
            "/connector/v1/pair",
            {
                "code": code,
                "sealingKey": keys.b64(sealing),
                "sealingSignature": keys.b64(signature),
                "version": "0.1.0-test",
            },
        )


@pytest.fixture
def admin(server, admin_client):
    with server.db.tx() as s:
        settings.put(s, "publicUrl", ORIGIN, None)
    return admin_client


def pair_code(admin) -> str:
    r = admin.post("/ui/api/settings/connector/pairings")
    assert r.status_code == 201, r.text
    out = r.json()
    assert out["code"].startswith("mkp1.") and "moolakata-connector pair mkp1." in out["command"]
    return out["code"]


@pytest.fixture
def paired(server, admin, client):
    fake = FakeConnector(server, client)
    r = fake.pair(pair_code(admin))
    assert r.status_code == 200, r.text
    # The admin compared the fingerprints (S18.4.3): only then are credentials and files taken.
    assert admin.post("/ui/api/settings/connector/confirm").status_code == 200
    return fake


def test_a_connector_reporting_from_a_new_address_is_alerted_until_accepted(
    server, paired, admin, client
):
    """S18.2.4.4: the first address its reports come from is known; a change alerts admins,
    who accept it (the connector moved) or unpair (its host was lost)."""
    from conftest import ORIGIN
    from fastapi.testclient import TestClient

    from moolakata import alerts

    paired.call("/connector/v1/report", {"locked": False, "connections": []})
    view = admin.get("/ui/api/settings/connector").json()
    assert view["lastAddress"] == "127.0.0.1" and view["knownAddress"] == "127.0.0.1"
    moved = FakeConnector(server, TestClient(client.app, base_url=ORIGIN, client=("10.9.9.9", 1)))
    moved.key, moved.fp = paired.key, paired.fp
    assert (
        moved.call("/connector/v1/report", {"locked": False, "connections": []}).status_code == 200
    )
    view = admin.get("/ui/api/settings/connector").json()
    assert view["lastAddress"] == "10.9.9.9" and view["knownAddress"] == "127.0.0.1"
    alerts.evaluate(server)
    kinds_open = [a["kind"] for a in admin.get("/ui/api/alerts").json()["open"]]
    assert "connector-moved" in kinds_open
    assert admin.post("/ui/api/settings/connector/accept-address").status_code == 200
    view = admin.get("/ui/api/settings/connector").json()
    assert view["knownAddress"] == "10.9.9.9"
    alerts.evaluate(server)
    kinds_open = [a["kind"] for a in admin.get("/ui/api/alerts").json()["open"]]
    assert "connector-moved" not in kinds_open
    assert "connector.address-changed" in [a.kind for a in activity_rows(server)]


def test_an_unconfirmed_pairing_gets_no_credential_and_posts_no_file(server, admin, client):
    """S18.4.3: paired but not confirmed, the connector reports and is answered, but a sealed
    credential is withheld, a file is refused, and no sign-in can be sealed for it."""
    fake = FakeConnector(server, client)
    assert fake.pair(pair_code(admin)).status_code == 200
    view = admin.get("/ui/api/settings/connector").json()
    assert view["state"] == "paired" and view["confirmedAt"] is None
    alice = make_user(server, "alice").id
    cid = connection(server, alice)
    aid = account(server, alice, cid)
    out = fake.call("/connector/v1/report", {"locked": False, "connections": []}).json()
    assert out["connections"][0]["sealed"] is None
    r = fake.call(
        f"/connector/v1/accounts/{aid}/files",
        raw=b"--x\r\n",
        headers={"Content-Type": "multipart/form-data; boundary=x"},
    )
    assert r.status_code == 403 and r.json()["code"] == "not-confirmed"
    c = sign_in(server, "alice")
    assert c.get("/ui/api/connector").json()["confirmed"] is False
    r = c.post(f"/ui/api/profile/connections/{cid}/credential", json={"sealed": "x" * 100})
    assert r.status_code == 409 and r.json()["code"] == "pairing-unconfirmed"
    assert admin.post("/ui/api/settings/connector/confirm").status_code == 200
    view = admin.get("/ui/api/settings/connector").json()
    assert view["confirmedAt"] and view["confirmedBy"]
    out = fake.call("/connector/v1/report", {"locked": False, "connections": []}).json()
    assert out["connections"][0]["sealed"]["ciphertext"] == "c2VhbGVk"
    assert "connector.confirmed" in [a.kind for a in activity_rows(server)]


def test_a_report_names_its_page_and_the_answer_says_whether_confirmed(server, admin, client):
    """S18.11.1, S18.11.3: the connector's page, from its reports, for Settings › Connector to
    link to (an https host and port, nothing else); the answer says whether an admin confirmed
    the pairing, which its page shows."""
    fake = FakeConnector(server, client)
    assert fake.pair(pair_code(admin)).status_code == 200

    def report(**extra) -> dict:
        r = fake.call("/connector/v1/report", {"locked": True, "connections": [], **extra})
        assert r.status_code == 200, r.text
        return r.json()

    page = "https://connector.griffin.home:37374"
    assert report(page=page)["confirmed"] is False
    assert admin.get("/ui/api/settings/connector").json()["page"] == page
    for bad in (
        "http://connector.lan:37374",
        "https://u:p@connector.lan",
        "https://connector.lan/somewhere",
        "https://connector.lan:37374/?next=x",
        "https://connector.lan:port",
        "javascript:alert(1)",
        "https://",
        7,
    ):
        report(page=bad)
        assert admin.get("/ui/api/settings/connector").json()["page"] is None, bad
    assert admin.post("/ui/api/settings/connector/confirm").status_code == 200
    assert report(page=page)["confirmed"] is True
    report()  # a connector that names no page any more
    assert admin.get("/ui/api/settings/connector").json()["page"] is None


def test_pairing_takes_the_code_once_and_records_the_keys(server, admin, client):
    fake = FakeConnector(server, client)
    hello = client.get("/connector/v1/hello").json()
    assert hello["protocol"] == PROTOCOL and hello["fingerprint"] == fake.fp
    code = pair_code(admin)
    view = admin.get("/ui/api/settings/connector").json()
    assert view["state"] == "pairing" and view["codeExpiresAt"]
    r = fake.pair(code)
    out = r.json()
    assert out["fingerprint"] == fake.fp
    assert out["connectorFingerprint"] == keys.fingerprint(keys.raw_public(fake.key.public_key()))
    view = admin.get("/ui/api/settings/connector").json()
    assert view["state"] == "paired" and view["locked"] is True
    assert view["fingerprint"] == keys.short(out["connectorFingerprint"])
    assert view["sealingKey"] == keys.b64(b"\x11" * 32)
    assert view["connectorVersion"] == "0.1.0-test"
    # The code worked once.
    again = FakeConnector(server, client).pair(code)
    assert again.status_code == 403 and again.json()["code"] == "code-used"
    with server.db.read() as s:
        row = manage.paired(s)
        assert row.codeHash is None and row.identityKey == keys.b64(
            keys.raw_public(fake.key.public_key())
        )


def test_a_pairing_code_needs_the_address_and_expires(server, admin_client, admin, client):
    with server.db.tx() as s:
        settings.put(s, "publicUrl", None, None)
    r = admin.post("/ui/api/settings/connector/pairings")
    assert r.status_code == 422 and r.json()["code"] == "no-address"
    with server.db.tx() as s:
        settings.put(s, "publicUrl", ORIGIN, None)
    code = pair_code(admin)
    clock.fix(dt.datetime.now(dt.UTC) + dt.timedelta(hours=25))
    try:
        r = FakeConnector(server, client).pair(code)
    finally:
        clock.fix(None)
    assert r.status_code == 403 and r.json()["code"] == "code-used"


def test_calls_are_signed_and_answers_are_signed_back(server, paired, client):
    r = paired.call("/connector/v1/report", {"locked": True, "connections": []})
    assert r.status_code == 200, r.text
    assert r.json() == {"connections": [], "removed": [], "confirmed": True}
    # Unsigned, a stranger's key, and a replay are refused (signed when there is a nonce).
    r = client.post("/connector/v1/report", json={}, headers={"Origin": ORIGIN})
    assert r.status_code == 403 and r.json()["code"] == "unsigned"
    stranger = FakeConnector(server, client)
    r = stranger.call("/connector/v1/report", {})
    assert r.status_code == 403 and r.json()["code"] == "not-paired"
    body = b"{}"
    signed = signing.sign_request(
        paired.key, "POST", "/connector/v1/report", body, paired.fp, scheme=signing.CONN
    )
    h = {**signed.headers, "Content-Type": "application/json"}
    assert client.post("/connector/v1/report", content=body, headers=h).status_code == 200
    r = client.post("/connector/v1/report", content=body, headers=h)
    assert r.status_code == 403 and r.json()["code"] == "replayed"
    r = paired.call("/connector/v1/report", {}, headers={"MK-Conn-Protocol": "9"})
    assert r.status_code == 426 and "speaks connector protocol 1" in r.json()["message"]


def connection(server, owner_id: str, label="Alice's Schwab login", driver="schwab") -> str:
    with server.db.tx() as s:
        row = manage.paired(s)
        c = Connection(
            id=ids.new_id("Conn"),
            ownerId=owner_id,
            connectorId=row.id,
            driver=driver,
            label=label,
            state="new",
            sealedCredential="c2VhbGVk",
            sealedAt=clock.now(),
        )
        s.add(c)
        return c.id


def account(server, owner_id: str, connection_id: str | None = None, **kw) -> str:
    with server.db.tx() as s:
        a = Account(
            id=ids.new_id("Acct"),
            ownerId=owner_id,
            name=kw.get("name", "Everyday Checking"),
            type=kw.get("type", "checking"),
            institution=kw.get("institution", "UMB"),
            connectionId=connection_id,
            syncAccount="Checking ••4417" if connection_id else None,
        )
        s.add(a)
        return a.id


def test_a_report_updates_connections_and_answers_with_the_work_waiting(server, paired, admin):
    alice = make_user(server, "alice").id
    cid = connection(server, alice)
    aid = account(server, alice, cid)
    r = paired.call(
        "/connector/v1/report",
        {
            "locked": False,
            "connections": [
                {
                    "id": cid,
                    "state": "ok",
                    "message": "14 new",
                    "lastRunAt": "2026-10-15T05:40:12Z",
                    "lastRunAdded": 14,
                    "institutionAccounts": [
                        {"name": "Individual", "last4": "4417"},
                        {"name": "Rollover IRA", "last4": "123456780921"},
                        {"name": "x", "last4": "ab"},
                    ],
                },
                {"id": "Conn_unknown", "state": "ok"},
            ],
        },
    )
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["removed"] == []
    (c,) = out["connections"]
    assert c["id"] == cid and c["ownerName"] == "Alice" and c["driver"] == "schwab"
    assert c["accounts"] == [
        {"id": aid, "syncAccount": "Checking ••4417", "formats": ["ofx", "csv", "statement"]}
    ]
    assert c["sealed"]["ciphertext"] == "c2VhbGVk"
    view = admin.get("/ui/api/settings/connector").json()
    assert view["locked"] is False and view["lastReportAt"]
    (shown,) = view["connections"]
    assert shown["state"] == "ok" and shown["message"] == "14 new" and shown["lastRunAdded"] == 14
    assert shown["institutionAccounts"] == [
        {"name": "Individual", "last4": "4417"},
        {"name": "Rollover IRA", "last4": "0921"},
        {"name": "x", "last4": None},
    ]
    assert (
        shown["credentialWaiting"] is True and shown["accounts"][0]["name"] == "Everyday Checking"
    )
    # Taken: MoolaKata deletes its copy of the sealed credential, the box the call names
    # (protocol §4.3.2); naming another leaves the one waiting.
    at = c["sealed"]["sealedAt"]
    r = paired.call(f"/connector/v1/connections/{cid}/credential/taken", {"sealedAt": "older"})
    assert r.status_code == 200
    out = paired.call("/connector/v1/report", {"locked": False, "connections": []}).json()
    assert out["connections"][0]["sealed"]["sealedAt"] == at
    r = paired.call(f"/connector/v1/connections/{cid}/credential/taken", {"sealedAt": at})
    assert r.status_code == 200
    out = paired.call("/connector/v1/report", {"locked": False, "connections": []}).json()
    assert out["connections"][0]["sealed"] is None
    r = paired.call("/connector/v1/connections/Conn_nothere/credential/taken", {})
    assert r.status_code == 404
    # A sign-in address for the owner (S18.7.1): Schwab's own page, and no other.
    page = "https://api.schwabapi.com/v1/oauth/authorize?client_id=KEY&state=s"
    r = paired.call(f"/connector/v1/connections/{cid}/sign-in", {"address": page})
    assert r.status_code == 200
    with server.db.read() as s:
        c = s.get(Connection, cid)
        assert c.state == "needs-sign-in" and c.signInAddress == page
    r = paired.call(
        f"/connector/v1/connections/{cid}/sign-in", {"address": "https://schwab.evil/oauth"}
    )
    assert r.status_code == 403 and r.json()["code"] == "address-invalid"
    r = paired.call(f"/connector/v1/connections/{cid}/sign-in", {"address": "http://x"})
    assert r.status_code == 403 and r.json()["code"] == "address-invalid"


def _multipart(file: bytes, meta: dict, name="schwab.ofx") -> tuple[bytes, str]:
    boundary = "mk-boundary"
    body = (
        (
            f'--{boundary}\r\nContent-Disposition: form-data; name="meta"\r\n'
            f"Content-Type: application/json\r\n\r\n{json.dumps(meta)}\r\n"
            f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{name}"\r\n'
            f"Content-Type: application/octet-stream\r\n\r\n"
        ).encode()
        + file
        + f"\r\n--{boundary}--\r\n".encode()
    )
    return body, f"multipart/form-data; boundary={boundary}"


def test_a_posted_file_goes_through_the_import_once(server, paired):
    alice = make_user(server, "alice").id
    cid = connection(server, alice)
    aid = account(server, alice, cid)
    other = account(server, alice, name="Savings")
    body, ctype = _multipart(OFX, {"connectionId": cid, "format": "ofx"})
    r = paired.call(
        f"/connector/v1/accounts/{aid}/files", raw=body, headers={"Content-Type": ctype}
    )
    assert r.status_code == 200, r.text
    assert r.json() == {"imported": {"added": 2, "matched": 0, "changed": 0}, "kept": False}
    r = paired.call(
        f"/connector/v1/accounts/{aid}/files", raw=body, headers={"Content-Type": ctype}
    )
    assert r.json()["imported"] == {"added": 0, "matched": 2, "changed": 0}, "idempotent"
    with server.db.read() as s:
        assert s.query(Transaction).filter_by(accountId=aid).count() == 2
        imp = s.query(Import).filter_by(accountId=aid).first()
        assert imp.userId == alice and imp.format == "ofx"
    # Activity names the connector and the Connection (S18.8), never an amount.
    c = sign_in(server, "alice")
    acts = c.get("/ui/api/activity").json()["items"]
    mine = [a for a in acts if a.get("via")]
    assert mine and mine[0]["via"] == "MoolaKata Connector, Alice's Schwab login"
    assert "42.37" not in json.dumps(acts)
    # An account whose sync doesn't name this Connection is refused.
    r = paired.call(
        f"/connector/v1/accounts/{other}/files", raw=body, headers={"Content-Type": ctype}
    )
    assert r.status_code == 403 and r.json()["code"] == "account-not-synced"
    # The hash in the meta must match.
    body, ctype = _multipart(OFX, {"connectionId": cid, "sha256": "0" * 64})
    r = paired.call(
        f"/connector/v1/accounts/{aid}/files", raw=body, headers={"Content-Type": ctype}
    )
    assert r.status_code == 403 and r.json()["code"] == "file-refused"
    # A CSV with no saved mapping says so.
    body, ctype = _multipart(b"Date,Amount,Payee\n2026-09-01,-1.00,X\n", {"connectionId": cid})
    r = paired.call(
        f"/connector/v1/accounts/{aid}/files", raw=body, headers={"Content-Type": ctype}
    )
    assert r.status_code == 403 and r.json()["code"] == "mapping-missing"


def test_a_posted_statement_is_kept_without_reading_once(server, paired):
    alice = make_user(server, "alice").id
    cid = connection(server, alice, driver="ofx-direct")
    aid = account(server, alice, cid)
    pdf = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"
    body, ctype = _multipart(pdf, {"connectionId": cid}, name="umb-2026-09.pdf")
    r = paired.call(
        f"/connector/v1/accounts/{aid}/files", raw=body, headers={"Content-Type": ctype}
    )
    assert r.status_code == 200, r.text
    assert r.json() == {"imported": None, "kept": True, "repeated": False}
    r = paired.call(
        f"/connector/v1/accounts/{aid}/files", raw=body, headers={"Content-Type": ctype}
    )
    assert r.json()["repeated"] is True
    with server.db.read() as s:
        imps = s.query(Import).filter_by(accountId=aid).all()
        assert len(imps) == 1 and imps[0].format == "kept"
    c = sign_in(server, "alice")
    receipts = c.get("/ui/api/receipts").json()["items"]
    assert len(receipts) == 1 and receipts[0]["payee"].endswith("statement")


def test_the_owners_upload_limit_counts_the_connectors_posts(server, paired):
    alice = make_user(server, "alice").id
    cid = connection(server, alice)
    aid = account(server, alice, cid)
    for _ in range(60):
        server.upload_rate.hit(alice)
    body, ctype = _multipart(OFX, {"connectionId": cid})
    r = paired.call(
        f"/connector/v1/accounts/{aid}/files", raw=body, headers={"Content-Type": ctype}
    )
    assert r.status_code == 429 and r.json()["code"] == "limit" and r.headers["Retry-After"]


def test_unpair_stops_every_connection_and_turns_sync_off(server, paired, admin, client):
    alice = make_user(server, "alice").id
    cid = connection(server, alice)
    aid = account(server, alice, cid)
    r = admin.post("/ui/api/settings/connector/unpair")
    assert r.status_code == 200 and r.json()["state"] == "none"
    with server.db.read() as s:
        assert s.get(Connection, cid).state == "removed"
        assert s.get(Account, aid).connectionId is None
    r = paired.call("/connector/v1/report", {})
    assert r.status_code == 403 and r.json()["code"] == "not-paired"
    assert admin.post("/ui/api/settings/connector/unpair").status_code == 404
    # Pairing another replaces the one paired (S18.4.3).
    first = FakeConnector(server, client)
    assert first.pair(pair_code(admin)).status_code == 200
    second = FakeConnector(server, client)
    assert second.pair(pair_code(admin)).status_code == 200
    assert first.call("/connector/v1/report", {}).status_code == 403
    assert second.call("/connector/v1/report", {}).status_code == 200
    # And the connector's own unpair ends it here.
    assert second.call("/connector/v1/unpaired", {}).json()["state"] == "ended"
    assert admin.get("/ui/api/settings/connector").json()["state"] == "none"
    with server.db.read() as s:
        assert [r.state for r in s.query(Connector).order_by(Connector.createdAt)] == [
            "ended",
            "ended",
            "ended",
        ]


def test_pairing_and_unpairing_need_the_password_again(server, admin, monkeypatch):
    from moolakata.ui import deps

    monkeypatch.setattr(deps, "REAUTH_MINUTES", 0)
    clock.fix(dt.datetime.now(dt.UTC) + dt.timedelta(minutes=1))
    try:
        r = admin.post("/ui/api/settings/connector/pairings")
    finally:
        clock.fix(None)
    assert r.status_code == 403 and r.json()["code"] == "reauth-required"


def test_the_connector_alerts_admins_when_locked_or_silent(server, paired, admin, frozen_clock):
    paired.call("/connector/v1/report", {"locked": True, "connections": []})
    alerts.evaluate(server)
    titles = [a["title"] for a in admin.get("/ui/api/alerts").json()["open"]]
    assert "The MoolaKata Connector is locked" in titles
    paired.call("/connector/v1/report", {"locked": False, "connections": []})
    alerts.evaluate(server)
    open_ = admin.get("/ui/api/alerts").json()["open"]
    assert not any("Connector" in a["title"] for a in open_)
    clock.fix(clock.now() + dt.timedelta(minutes=16))
    alerts.evaluate(server)
    open_ = admin.get("/ui/api/alerts").json()["open"]
    assert any(a["title"] == "The MoolaKata Connector hasn't been heard from" for a in open_)
    view = admin.get("/ui/api/settings/connector").json()
    assert view["silentForSeconds"] and view["silentForSeconds"] >= 60


def test_a_connection_that_needs_a_sign_in_alerts_its_owner_and_admins(server, paired, admin):
    alice = make_user(server, "alice").id
    cid = connection(server, alice)
    paired.call(
        "/connector/v1/report",
        {
            "locked": False,
            "connections": [{"id": cid, "state": "needs-sign-in", "message": "weekly"}],
        },
    )
    alerts.evaluate(server)
    c = sign_in(server, "alice")
    mine = c.get("/ui/api/alerts").json()["open"]
    assert [a["title"] for a in mine] == ["Alice's Schwab login needs a sign-in"]
    assert mine[0]["fix"] == "Sign in again"
    theirs = admin.get("/ui/api/alerts").json()["open"]
    assert any(a["title"] == "Alice's Schwab login needs a sign-in" for a in theirs)


def test_an_admin_who_owns_the_connection_is_alerted_once(server, paired, admin):
    # S12.11.2: one alert per cause; an admin who owns what failed has the owner's alert, with
    # its own way to fix it, and another admin has the admins' one.
    me = admin.get("/ui/api/session").json()["user"]
    make_user(server, "root2", admin=True)
    cid = connection(server, me["id"])
    paired.call(
        "/connector/v1/report",
        {
            "locked": False,
            "connections": [{"id": cid, "state": "needs-sign-in", "message": "weekly"}],
        },
    )
    opened = alerts.evaluate(server)
    mine = [a for a in admin.get("/ui/api/alerts").json()["open"] if "sign-in" in a["title"]]
    assert [(a["title"], a["fix"]) for a in mine] == [
        ("Alice's Schwab login needs a sign-in", "Sign in again")
    ]
    other = sign_in(server, "root2")
    theirs = [a for a in other.get("/ui/api/alerts").json()["open"] if "sign-in" in a["title"]]
    assert [a["fix"] for a in theirs] == ["Connector settings"]
    with server.db.read() as s:
        told = sorted(u.username for a in opened for u in alerts.recipients(s, a))
    assert told == sorted([me["username"], "root2"])


@pytest.fixture
def frozen_clock():
    clock.fix(dt.datetime(2026, 10, 15, 12, 0, tzinfo=dt.UTC))
    yield
    clock.fix(None)


def test_network_ranges_decide_who_reaches_each_path(server, admin):
    version = admin.get("/ui/api/settings").json()["version"]
    r = admin.patch(
        "/ui/api/settings",
        json={"networkAppRanges": ["10.0.0.0/8", "bad"]},
        headers={"If-Match": f'"{version}"'},
    )
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "networkAppRanges"
    r = admin.patch(
        "/ui/api/settings",
        json={"networkLinkRanges": ["10.0.0.0/8"], "networkConnectorRanges": ["192.168.1.7"]},
        headers={"If-Match": f'"{version}"'},
    )
    assert r.status_code == 200, r.text
    assert r.json()["values"]["networkConnectorRanges"] == ["192.168.1.7/32"]
    # The test client calls from testclient (not an address), which no range allows; the app's
    # own ranges stay empty, so /ui still answers.
    assert admin.get("/ui/api/settings").status_code == 200
    with new_client(server) as c:
        assert c.get("/link/v1/hello").status_code == 404
        assert c.get("/connector/v1/hello").status_code == 404
        assert c.get("/healthz").status_code == 200
    from moolakata.middleware import AddressRanges

    assert AddressRanges._allowed("192.168.1.7", ["192.168.1.7/32"])
    assert AddressRanges._allowed("::ffff:192.168.1.7", ["192.168.1.0/24"])
    assert not AddressRanges._allowed("192.168.2.7", ["192.168.1.0/24"])
    assert AddressRanges._allowed("anything", [])
    assert AddressRanges._allowed("100.100.1.1", settings.LAN_AND_OVERLAY)
    assert not AddressRanges._allowed("8.8.8.8", settings.LAN_AND_OVERLAY)


def activity_rows(server):
    from moolakata.store.entities.core import Activity

    with server.db.read() as s:
        return list(s.query(Activity))


def test_a_sealing_key_its_identity_key_didnt_sign_is_refused(server, admin, client):
    # K24: browsers seal only to the key of the connector an admin confirmed (S18.4.5).
    fake = FakeConnector(server, client)
    r = fake.pair(pair_code(admin), signed=False)
    assert r.status_code == 403 and r.json()["code"] == "sealing-unsigned"
    assert admin.get("/ui/api/settings/connector").json()["state"] == "pairing"


def test_unpair_ends_the_pairing_and_any_code_still_out(server, admin, client, paired):
    # K20: after Pair, then Unpair, no connector stays paired and the code can't be used.
    code = pair_code(admin)
    assert admin.post("/ui/api/settings/connector/unpair").status_code == 200
    assert admin.get("/ui/api/settings/connector").json()["state"] in (None, "ended", "none")
    late = FakeConnector(server, client)
    assert late.pair(code).json()["code"] == "code-used"
    assert paired.call("/connector/v1/report", {"locked": False}).json()["code"] == "not-paired"


def test_a_new_address_stays_alerted_until_an_admin_accepts_it(server, admin, paired):
    # K20: the genuine connector reporting again from its own address doesn't clear a
    # thief's (S18.5.4).
    from moolakata import alerts
    from moolakata.connector import manage

    def report(address):
        with server.db.read() as s:
            row = manage.paired(s)
        manage.apply_report(server, row, {"locked": False}, "0.1.0", 1, address=address)

    def moved() -> bool:
        from moolakata.store.entities.alerts import Alert

        alerts.evaluate(server)
        with server.db.read() as s:
            return (
                s.query(Alert).filter_by(kind="connector-moved", resolvedAt=None).first()
                is not None
            )

    report("192.0.2.10")
    report("198.51.100.7")  # from somewhere else
    report("192.0.2.10")  # and the known one again
    assert moved()
    assert admin.get("/ui/api/settings/connector").json()["newAddress"] == "198.51.100.7"
    assert admin.post("/ui/api/settings/connector/accept-address").status_code == 200
    view = admin.get("/ui/api/settings/connector").json()
    assert view["knownAddress"] == "198.51.100.7" and view["newAddress"] is None
    assert not moved()
