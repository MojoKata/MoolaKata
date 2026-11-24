"""The links code's parts on their own (requirements S11.1.3, link-protocol.md §3, §7): each
refusal pinned at its code and in its words, in process, without a second server."""

import pytest
from sqlalchemy import select
from test_gate import Side, link_side  # noqa: F401

from moolakata.links import keys, signing
from moolakata.store.entities.users import User

# ---------- signing (link-protocol.md §3)


def _key():
    return signing.Ed25519PrivateKey.generate()


def _headers(signed: signing.Signed) -> dict[str, str]:
    return {k.lower(): v for k, v in signed.headers.items()}


def test_an_asked_call_with_an_unreadable_key_names_no_caller():
    asked = signing.asked_of({"mk-link-nonce": "n" * 16, "mk-link-key": "a"}, b"{}")
    assert asked == signing.Asked("n" * 16, "", signing.body_hash(b"{}"))
    assert signing.asked_of({"mk-link-key": "a"}, b"{}") is None, "no nonce, no call"


@pytest.mark.parametrize(
    ("scheme", "who"), [(signing.LINK, "linked server"), (signing.CONN, "server")]
)
def test_an_answer_unsigned_or_from_a_clock_a_minute_off_is_refused(scheme, who):
    k = _key()
    asked = signing.Asked("n" * 16, "f" * 64, signing.body_hash(b"{}"))
    for headers in ({}, {scheme.h("Time"): "x", scheme.h("Signature"): "AA"}):
        with pytest.raises(signing.Refused) as e:
            signing.verify_answer(b"", 200, b"{}", asked, headers, scheme=scheme)
        assert (e.value.code, e.value.message) == (
            "answer-unsigned",
            f"The {who}'s answer wasn't signed.",
        )
    signed = signing.sign_answer(k, 200, b"{}", asked, now=1000, scheme=scheme)
    public = keys.raw_public(k.public_key())
    signing.verify_answer(public, 200, b"{}", asked, signed, now=1060, scheme=scheme)
    with pytest.raises(signing.Refused) as e:
        signing.verify_answer(public, 200, b"{}", asked, signed, now=1061, scheme=scheme)
    assert (e.value.code, e.value.message) == (
        "clock-skew",
        f"The {who}'s clock is more than a minute off.",
    )


def test_a_call_with_a_short_key_or_a_nonce_out_of_bounds_is_unsigned():
    k = _key()
    fp = "f" * 64
    good = _headers(signing.sign_request(k, "POST", "/p", b"", fp))
    for change in (
        {"mk-link-key": keys.b64(b"k" * 31)},
        {"mk-link-nonce": "n" * 7},
        {"mk-link-nonce": "n" * 65},
    ):
        with pytest.raises(signing.Refused) as e:
            signing.verify_request({**good, **change}, "POST", "/p", b"", fp, signing.Nonces())
        assert (e.value.code, e.value.message) == (
            "unsigned",
            "A linked server's call must be signed.",
        )
    with pytest.raises(signing.Refused) as e:
        signing.verify_request({}, "POST", "/p", b"", fp, signing.Nonces(), scheme=signing.CONN)
    assert e.value.message == "The connector's call must be signed."


def test_a_nonce_is_forgotten_two_minutes_after_it_was_seen():
    now = [1000.0]
    nonces = signing.Nonces(clock=lambda: now[0])
    assert nonces.first("k", "n1") and nonces.first("k", "n2")
    assert not nonces.first("k", "n1"), "a replay within two minutes"
    now[0] += signing.NONCE_SECONDS
    assert not nonces.first("k", "n1"), "still within them at the edge"
    now[0] += 1
    assert nonces.first("k", "n1"), "forgotten after them"
    assert nonces.first("k", "n2")


# ---------- calling a peer (link-protocol.md §3, §7)


ADDRESS = "https://peer.test"


@pytest.fixture
def peer(server, monkeypatch):
    """This server, a peer's key, and `answer(fn)`: every call it makes answered by `fn`, given
    the request, as the network would answer it."""
    import httpx

    from moolakata import net

    k = _key()

    def answer(fn):
        monkeypatch.setattr(net, "network", lambda g, p: httpx.MockTransport(fn))

    return server, k, keys.raw_public(k.public_key()), answer


def _signed_answer(k, request, status: int, body: bytes, digest=None) -> dict:
    """The answer's signature headers, over the call it answers."""
    h = {name.lower(): v for name, v in request.headers.items()}
    asked = signing.Asked(
        h["mk-link-nonce"],
        keys.fingerprint(keys.unb64(h["mk-link-key"])),
        h["mk-link-body-sha256"],
    )
    return signing.sign_answer(k, status, body, asked, digest=digest)


@pytest.mark.parametrize(
    "address",
    [
        "http://peer.test",
        "https://",
        "https://peer.test/?x=1",
        "https://peer.test/#x",
        "https://[::1",
        "",
    ],
)
def test_a_link_address_that_isnt_https_with_a_host_alone_is_refused(address):
    from moolakata.links import client

    with pytest.raises(client.LinkError) as e:
        client.checked_address(address)
    assert (e.value.code, e.value.message) == (
        "address-invalid",
        "A link address is https://, with a host and nothing after its path.",
    )
    assert client.checked_address(" https://peer.test/mk/ ") == "https://peer.test/mk"


def test_a_hello_that_isnt_a_moolakata_servers_is_refused(peer):
    import httpx

    from moolakata.links import client

    srv, _, _, answer = peer
    answer(lambda r: httpx.Response(404, text="Not Found"))
    with pytest.raises(client.LinkError) as e:
        client.hello(srv, ADDRESS)
    assert (e.value.code, e.value.message) == (
        "not-moolakata",
        "https://peer.test doesn't answer as a MoolaKata server.",
    )


def test_a_receipt_refused_or_unsigned_is_never_taken(peer):
    import hashlib

    import httpx

    from moolakata.links import client

    srv, k, public, answer = peer
    answer(lambda r: httpx.Response(404, json={"code": "not-shared"}))
    with pytest.raises(client.LinkError) as e:
        list(client.iter_file(srv, ADDRESS, public, "Rcpt_x", []))
    assert (e.value.code, e.value.message) == ("file-refused", "The file was refused (404).")
    answer(lambda r: httpx.Response(200, content=b"sealed"))
    got: list[str] = []
    with pytest.raises(client.LinkError) as e:
        list(client.iter_file(srv, ADDRESS, public, "Rcpt_x", got))
    assert (e.value.code, e.value.message) == (
        "answer-unsigned",
        "The linked server's answer wasn't signed.",
    )
    assert got == [], "no digest is given for bytes no signature covers"
    digest = hashlib.sha256(b"sealed").hexdigest()
    answer(
        lambda r: httpx.Response(
            200, content=b"sealed", headers=_signed_answer(k, r, 200, b"", digest)
        )
    )
    assert b"".join(client.iter_file(srv, ADDRESS, public, "Rcpt_x", got)) == b"sealed"
    assert got == [digest]


def test_a_receipt_sent_to_a_peer_unreachable_limiting_or_not_signing_is_refused(peer, tmp_path):
    import hashlib

    import httpx

    from moolakata.links import client

    srv, k, public, answer = peer
    sealed = tmp_path / "r.mkr"
    sealed.write_bytes(b"sealed")
    digest = hashlib.sha256(b"sealed").hexdigest()

    def send():
        with pytest.raises(client.LinkError) as e:
            client.send_file(srv, ADDRESS, public, "Rcpt_x", sealed, digest)
        return e.value.code, e.value.message

    def down(r):
        raise httpx.ConnectError("down")

    answer(down)
    assert send() == ("unreachable", "https://peer.test didn't answer (ConnectError).")
    answer(lambda r: httpx.Response(429, json={"code": "limit"}))
    assert send() == ("limit", "The other server is limiting calls; it is asked again later.")
    answer(lambda r: httpx.Response(200, json={"ok": True}))
    assert send() == ("answer-unsigned", "The linked server's answer wasn't signed.")
    seen = []

    def kept(r):
        seen.append(r.url.params.get_list("file"))
        body = b'{"ok":true}'
        return httpx.Response(200, content=body, headers=_signed_answer(k, r, 200, body))

    answer(kept)
    client.send_file(srv, ADDRESS, public, "Rcpt_x", sealed, digest)
    assert seen == [["Rcpt_x"]]


# ---------- the routes a peer calls (link-protocol.md §4, §7)


def _post(side, path: str, data: dict):
    import json

    body = json.dumps(data).encode()
    r = side.client.post(path, content=body, headers=side.headers(path, body))
    return r.status_code, r.json()


def test_a_receipt_not_shared_or_not_sealable_is_refused_not_shared(link_side, monkeypatch):  # noqa: F811
    # S11.5.1: `not-shared`, in this server's words, when no share includes it, and when the
    # peer's copy has no key to seal it to yet.
    from moolakata.links import serve

    assert _post(link_side, "/link/v1/file", {"id": "Rcpt_x"}) == (
        403,
        {"code": "not-shared", "message": "That receipt isn't shared."},
    )
    monkeypatch.setattr(serve, "allowed_file", lambda srv, link_id, rid: True)
    assert _post(link_side, "/link/v1/file", {"id": "Rcpt_x"}) == (
        403,
        {"code": "not-shared", "message": "the peer's copy has no access key yet"},
    )


def test_a_delivered_change_that_doesnt_check_is_refused_and_the_link_shows_it(link_side):  # noqa: F811
    # S11.7: refused `change-refused`, and recorded here as refused data, never as a failure.
    from moolakata.store.entities.links import Link

    assert _post(link_side, "/link/v1/deliver", {"change": {"seq": 1, "removed": []}}) == (
        403,
        {"code": "change-refused", "message": "change 1 fails its signature check"},
    )
    with link_side.srv.db.read(unscoped="test") as s:
        row = s.get(Link, link_side.counted)
        assert row.refusal == "change 1 fails its signature check"
        assert row.failingSince is None


def test_an_answer_failing_on_a_link_error_of_its_own_is_a_server_error(link_side, monkeypatch):  # noqa: F811
    # A route's own failure, never `busy`, is the gate's `server-error`, signed (§7).
    from moolakata.links import client, manage

    def gone(srv, link, body, version):
        raise client.LinkError("not-found", "No such link.")

    monkeypatch.setattr(manage, "answer_exchange", gone)
    assert _post(link_side, "/link/v1/exchange", {}) == (
        500,
        {"code": "server-error", "message": "This call failed here; it is logged."},
    )


# ---------- the handshake, approval, certificate and directory (link-protocol.md §4.1–§4.5)


def _a_link(srv, state="active") -> str:
    from moolakata import ids
    from moolakata.store.entities.links import Link

    with srv.db.tx(unscoped="test") as s:
        row = Link(
            id=ids.new_id("Link"),
            state=state,
            role="inviter",
            peerName="doe-parents",
            address=ADDRESS,
            peerKey=keys.b64(keys.raw_public(_key().public_key())),
        )
        s.add(row)
        return row.id


@pytest.mark.parametrize(
    ("code", "why"),
    [
        ("xyz", "That isn't a MoolaKata link code: it starts mkl1."),
        ("mkl1.a", "The link code is damaged: copy it again whole."),
        ("mkl1." + keys.b64(b"[1]"), "The link code is damaged: copy it again whole."),
        (
            "mkl1." + keys.b64(b'{"a": "x", "f": "y"}'),
            "The link code is damaged: copy it again whole.",
        ),
        ("mkl1." + keys.b64(b"{not json"), "The link code is damaged: copy it again whole."),
    ],
)
def test_a_link_code_that_isnt_one_is_refused(code, why):
    from moolakata.links import client, manage

    with pytest.raises(client.LinkError) as e:
        manage.decode_code(code)
    assert (e.value.code, e.value.message) == ("code-invalid", why)


def test_a_code_spread_over_lines_reads_whole():
    from moolakata.links import manage

    code = manage.encode_code("https://peer.test", "f" * 64, "secret")
    spread = "\n".join(code[i : i + 20] for i in range(0, len(code), 20))
    assert manage.decode_code(f"  {spread} ") == {
        "a": "https://peer.test",
        "f": "f" * 64,
        "c": "secret",
    }


def test_no_invitation_or_join_without_this_servers_own_address(server, peer):
    # S11.2: the other server must be told where to reach this one.
    import httpx

    from moolakata import settings
    from moolakata.links import client, manage

    srv, _, public, answer = peer
    no_address = (
        "no-address",
        "Set this server's link address (or its public URL) first, so the other server can "
        "reach it.",
    )
    with srv.db.tx(unscoped="test") as s:
        settings.put(s, "publicUrl", None, None)
        settings.put(s, "linkAddress", None, None)
        admin = s.scalars(select(User.id)).first()
    with pytest.raises(client.LinkError) as e:
        manage.invite(srv, admin)
    assert (e.value.code, e.value.message) == no_address
    hello = {"protocol": 1, "fingerprint": keys.fingerprint(public), "key": keys.b64(public)}
    answer(lambda r: httpx.Response(200, json=hello))
    code = manage.encode_code(ADDRESS, keys.fingerprint(public), "secret")
    with pytest.raises(client.LinkError) as e:
        manage.join(srv, code, admin)
    assert (e.value.code, e.value.message) == no_address


def test_an_invitation_answers_a_join_once_and_only_from_an_address_it_can_call(server):
    # link-protocol.md §4.1: a code used, expired or withdrawn is `code-used`; a joining
    # server's address that isn't one is refused at the join, and the invitation still waits.
    import datetime as dt

    from moolakata import clock, settings
    from moolakata.links import manage
    from moolakata.store.entities.links import Link

    with server.db.tx(unscoped="test") as s:
        settings.put(s, "publicUrl", "https://home.test", None)
        admin = s.scalars(select(User.id)).first()
    link, code = manage.invite(server, admin)
    secret = manage.decode_code(code)["c"]
    joiner = keys.raw_public(_key().public_key())
    out = manage.answer_join(server, joiner, {"code": secret, "address": "http://joiner.test"})
    assert out == {
        "error": (
            "address-invalid",
            "A link address is https://, with a host and nothing after its path.",
        )
    }
    with server.db.tx(unscoped="test") as s:
        row = s.get(Link, link.id)
        assert row.state == "invited" and row.peerKey is None, "it still waits"
        row.codeExpiresAt = clock.now() - dt.timedelta(seconds=1)
    out = manage.answer_join(server, joiner, {"code": secret, "address": "https://joiner.test"})
    assert out == {"error": ("code-used", "That link code was used, expired or withdrawn.")}


def test_a_certificate_presented_before_it_was_announced_is_pinned_by_the_announcement(server):
    # link-protocol.md §4.5: the announcement vouches for a key the peer presented early.
    from moolakata import clock
    from moolakata.links import manage
    from moolakata.store.entities.links import Link

    link_id = _a_link(server)
    old, new = "aa" * 32, "bb" * 32
    with server.db.tx(unscoped="test") as s:
        row = s.get(Link, link_id)
        row.peerCert, row.peerCertOffered = old, new
        row.lastError, row.failingSince = "a certificate key other than the one", clock.now()
    with server.db.read(unscoped="test") as s:
        row = s.get(Link, link_id)
    assert manage.answer_certificate(server, row, {"fingerprint": new}) == {"ok": True}
    with server.db.read(unscoped="test") as s:
        row = s.get(Link, link_id)
        assert (row.peerCert, row.peerCertNext, row.peerCertOffered) == (new, None, None)
        assert row.lastError is None and row.failingSince is None
    manage.answer_certificate(server, row, {"fingerprint": "not one"})
    with server.db.read(unscoped="test") as s:
        assert s.get(Link, link_id).peerCertNext is None, "anything else is none"


def test_a_link_ended_by_its_peer_twice_is_recorded_once(server):
    from moolakata.links import manage
    from moolakata.store.entities.core import Activity

    link_id = _a_link(server)
    manage.ended_by_peer(server, link_id)
    manage.ended_by_peer(server, link_id)
    with server.db.read(unscoped="test") as s:
        kinds = [e.kind for e in s.scalars(select(Activity)) if e.subjectId == link_id]
    assert kinds == ["link.ended-by-peer"]


def test_a_user_named_twice_in_a_directory_is_kept_once(server):
    from moolakata.links import manage
    from moolakata.store.entities.links import Link

    link_id = _a_link(server)
    users = [
        {"id": "u1", "username": "bart", "displayName": "Bart"},
        {"id": "u1", "username": "bart2", "displayName": "Bart again"},
    ]
    with server.db.tx(unscoped="test") as s:
        manage.apply_directory(s, s.get(Link, link_id), {"users": users})
    with server.db.read(unscoped="test") as s:
        kept = [
            (u.remoteId, u.displayName)
            for u in s.scalars(select(User).where(User.linkId == link_id))
        ]
    assert kept == [("u1", "Bart")]


# ---------- Settings › Linked Servers (S11.7)


def _refused(r) -> tuple[int, str, str]:
    return r.status_code, r.json()["code"], r.json()["detail"]


def test_an_admins_action_on_no_such_link_is_not_found(admin_client):
    no_such = (404, "not-found", "No such link.")
    for what in ("approve", "resume", "end", "pull", "lock", "accept-certificate"):
        r = admin_client.post(f"/ui/api/settings/links/Link_none/{what}")
        assert _refused(r) == no_such, what
    r = admin_client.post("/ui/api/settings/links/Link_none/reset-copy")
    assert _refused(r) == no_such


def test_no_certificate_waiting_is_refused_and_lock_now_answers_the_link(server, admin_client):
    # link-protocol.md §4.5: nothing to accept is refused at its code, in its words.
    link_id = _a_link(server)
    r = admin_client.post(f"/ui/api/settings/links/{link_id}/accept-certificate")
    assert _refused(r) == (422, "no-certificate", "No other certificate is waiting to be accepted.")
    r = admin_client.post(f"/ui/api/settings/links/{link_id}/lock")
    assert r.status_code == 200 and r.json()["id"] == link_id


def test_joining_from_a_dev_server_may_reach_the_inviting_one_on_this_machine(
    server, admin_client, monkeypatch
):
    # S13.5: a link code's address is never exempt from the guard, but between two dev servers
    # on one machine; the guard's list is put back after the join, whatever it answered.
    import dataclasses

    import httpx

    from moolakata import net
    from moolakata.links import manage

    server.config = dataclasses.replace(server.config, dev=True)
    reached = []

    def hello(r):
        reached.append(r.url.host)
        return httpx.Response(404)

    monkeypatch.setattr(net, "network", lambda g, p: httpx.MockTransport(hello))
    code = manage.encode_code("https://peer.test", "f" * 64, "secret")
    r = admin_client.post("/ui/api/settings/links/join", json={"code": code})
    assert _refused(r) == (
        422,
        "not-moolakata",
        "https://peer.test doesn't answer as a MoolaKata server.",
    )
    assert reached == ["peer.test"]
    hosts, named = server.guard.snapshot()
    assert "peer.test" not in hosts | set().union(*named.values()), "allowed for the join alone"


def test_resuming_a_link_that_isnt_paused_is_refused_in_its_words(server, admin_client):
    link_id = _a_link(server)
    r = admin_client.post(f"/ui/api/settings/links/{link_id}/resume")
    assert _refused(r) == (422, "state-invalid", "A link that is active can't be active.")


def test_what_is_shared_from_here_leaves_out_an_item_since_deleted(server, admin_client):
    # S11.7: the admin sees each item shared over the link, by its kind, owner and the people
    # it names, an item of someone else's among them; never one that is gone.
    from conftest import make_user, sign_in
    from edits import make, share

    from moolakata.links import manage
    from moolakata.store.entities.accounts import Account
    from moolakata.store.entities.links import Link

    link_id = _a_link(server)
    with server.db.tx(unscoped="test") as s:
        manage.apply_directory(
            s, s.get(Link, link_id), {"users": [{"id": "u1", "displayName": "Bart"}]}
        )
        bart = s.scalars(select(User.id).where(User.linkId == link_id)).one()
    make_user(server, "jane")
    jane = sign_in(server, "jane")
    kept = make(jane, "Acct", name="Checking", type="checking").json()["id"]
    gone = make(jane, "Acct", name="Savings", type="savings").json()["id"]
    for acct in (kept, gone):
        assert share(jane, "account", acct, users={bart: "read"}).status_code == 200

    def outgoing():
        (row,) = admin_client.get("/ui/api/settings/links").json()["links"]
        return [(x["kind"], x["names"]) for x in row["outgoing"]]

    assert outgoing() == [("account", ["Bart"]), ("account", ["Bart"])]
    with server.db.tx(unscoped="test") as s:
        s.get(Account, gone).mark_deleted(None)
    assert outgoing() == [("account", ["Bart"])]
